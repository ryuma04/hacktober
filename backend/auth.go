package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"database/sql"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"regexp"
	"strings"
	"time"

	_ "github.com/lib/pq"
	"golang.org/x/crypto/bcrypt"
)

// User represents a registered DepExit user.
type User struct {
	ID        int       `json:"id"`
	Email     string    `json:"email"`
	CreatedAt time.Time `json:"created_at"`
}

type AuthDB struct {
	db *sql.DB
}

// Gmail regex pattern: must end with @gmail.com (case-insensitive)
var gmailRegex = regexp.MustCompile(`^[a-zA-Z0-9._%+-]+@gmail\.com$`)

// InitAuthDB connects to Neon PostgreSQL and creates the users table if needed.
func InitAuthDB(databaseURL string) (*AuthDB, error) {
	if databaseURL == "" {
		return nil, errors.New("DATABASE_URL is not set")
	}

	db, err := sql.Open("postgres", databaseURL)
	if err != nil {
		return nil, fmt.Errorf("failed to open postgres connection: %w", err)
	}

	db.SetMaxOpenConns(10)
	db.SetMaxIdleConns(5)
	db.SetConnMaxLifetime(10 * time.Minute)

	// Ping database
	if err := db.Ping(); err != nil {
		return nil, fmt.Errorf("failed to ping neon postgres: %w", err)
	}

	schema := `
	CREATE TABLE IF NOT EXISTS users (
		id SERIAL PRIMARY KEY,
		email VARCHAR(255) UNIQUE NOT NULL,
		password_hash VARCHAR(255) NOT NULL,
		created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
	);
	CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
	`
	if _, err := db.Exec(schema); err != nil {
		return nil, fmt.Errorf("failed to initialize database schema: %w", err)
	}

	log.Println("[Neon DB] Connected and verified users table successfully")
	return &AuthDB{db: db}, nil
}

// ValidateGmail validates that the email matches the Gmail regex.
func ValidateGmail(email string) bool {
	return gmailRegex.MatchString(strings.ToLower(strings.TrimSpace(email)))
}

// Simple standard-library JWT implementation to avoid bulky third-party dependencies:
type JWTClaims struct {
	UserID int    `json:"uid"`
	Email  string `json:"email"`
	Exp    int64  `json:"exp"`
}

func GenerateToken(userID int, email, secret string) (string, error) {
	header := base64.RawURLEncoding.EncodeToString([]byte(`{"alg":"HS256","typ":"JWT"}`))
	claims := JWTClaims{
		UserID: userID,
		Email:  email,
		Exp:    time.Now().Add(7 * 24 * time.Hour).Unix(),
	}
	claimsBytes, err := json.Marshal(claims)
	if err != nil {
		return "", err
	}
	payload := base64.RawURLEncoding.EncodeToString(claimsBytes)

	unsignedToken := header + "." + payload
	h := hmac.New(sha256.New, []byte(secret))
	h.Write([]byte(unsignedToken))
	signature := base64.RawURLEncoding.EncodeToString(h.Sum(nil))

	return unsignedToken + "." + signature, nil
}

func VerifyToken(tokenString, secret string) (*JWTClaims, error) {
	parts := strings.Split(tokenString, ".")
	if len(parts) != 3 {
		return nil, errors.New("invalid token format")
	}

	unsignedToken := parts[0] + "." + parts[1]
	h := hmac.New(sha256.New, []byte(secret))
	h.Write([]byte(unsignedToken))
	expectedSig := base64.RawURLEncoding.EncodeToString(h.Sum(nil))

	if !hmac.Equal([]byte(parts[2]), []byte(expectedSig)) {
		return nil, errors.New("invalid token signature")
	}

	claimsBytes, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return nil, errors.New("failed to decode claims")
	}

	var claims JWTClaims
	if err := json.Unmarshal(claimsBytes, &claims); err != nil {
		return nil, errors.New("failed to parse claims")
	}

	if claims.Exp < time.Now().Unix() {
		return nil, errors.New("token expired")
	}

	return &claims, nil
}

// Auth handlers
type AuthRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
}

type AuthResponse struct {
	Token string `json:"token"`
	User  User   `json:"user"`
}

func (a *API) register(w http.ResponseWriter, r *http.Request) {
	if a.authDB == nil {
		writeErr(w, http.StatusServiceUnavailable, "db_unavailable", "Database is not connected")
		return
	}

	var req AuthRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid_body", "Invalid JSON payload")
		return
	}

	email := strings.ToLower(strings.TrimSpace(req.Email))
	if !ValidateGmail(email) {
		writeErr(w, http.StatusBadRequest, "invalid_email", "Invalid email format. Only @gmail.com addresses are permitted.")
		return
	}

	if len(req.Password) < 6 {
		writeErr(w, http.StatusBadRequest, "invalid_password", "Password must be at least 6 characters")
		return
	}

	hashedPassword, err := bcrypt.GenerateFromPassword([]byte(req.Password), bcrypt.DefaultCost)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "hash_error", "Failed to hash password")
		return
	}

	var user User
	err = a.authDB.db.QueryRow(
		`INSERT INTO users (email, password_hash) VALUES ($1, $2) RETURNING id, email, created_at`,
		email, string(hashedPassword),
	).Scan(&user.ID, &user.Email, &user.CreatedAt)

	if err != nil {
		if strings.Contains(err.Error(), "duplicate key") || strings.Contains(err.Error(), "unique constraint") {
			writeErr(w, http.StatusConflict, "user_exists", "An account with this Gmail address already exists")
			return
		}
		writeErr(w, http.StatusInternalServerError, "db_error", "Failed to register user: "+err.Error())
		return
	}

	token, err := GenerateToken(user.ID, user.Email, a.cfg.JWTSecret)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "token_error", "Failed to generate session token")
		return
	}

	writeJSON(w, http.StatusCreated, AuthResponse{Token: token, User: user})
}

func (a *API) login(w http.ResponseWriter, r *http.Request) {
	if a.authDB == nil {
		writeErr(w, http.StatusServiceUnavailable, "db_unavailable", "Database is not connected")
		return
	}

	var req AuthRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid_body", "Invalid JSON payload")
		return
	}

	email := strings.ToLower(strings.TrimSpace(req.Email))
	if !ValidateGmail(email) {
		writeErr(w, http.StatusBadRequest, "invalid_email", "Invalid email format. Only @gmail.com addresses are permitted.")
		return
	}

	var user User
	var passwordHash string
	err := a.authDB.db.QueryRow(
		`SELECT id, email, password_hash, created_at FROM users WHERE email = $1`,
		email,
	).Scan(&user.ID, &user.Email, &passwordHash, &user.CreatedAt)

	if err != nil {
		writeErr(w, http.StatusUnauthorized, "invalid_credentials", "Invalid Gmail address or password")
		return
	}

	if err := bcrypt.CompareHashAndPassword([]byte(passwordHash), []byte(req.Password)); err != nil {
		writeErr(w, http.StatusUnauthorized, "invalid_credentials", "Invalid Gmail address or password")
		return
	}

	token, err := GenerateToken(user.ID, user.Email, a.cfg.JWTSecret)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "token_error", "Failed to generate session token")
		return
	}

	writeJSON(w, http.StatusOK, AuthResponse{Token: token, User: user})
}

func (a *API) me(w http.ResponseWriter, r *http.Request) {
	authHeader := r.Header.Get("Authorization")
	if !strings.HasPrefix(authHeader, "Bearer ") {
		writeErr(w, http.StatusUnauthorized, "unauthorized", "Missing Bearer token")
		return
	}

	token := strings.TrimPrefix(authHeader, "Bearer ")
	claims, err := VerifyToken(token, a.cfg.JWTSecret)
	if err != nil {
		writeErr(w, http.StatusUnauthorized, "invalid_token", err.Error())
		return
	}

	var user User
	err = a.authDB.db.QueryRow(
		`SELECT id, email, created_at FROM users WHERE id = $1`,
		claims.UserID,
	).Scan(&user.ID, &user.Email, &user.CreatedAt)

	if err != nil {
		writeErr(w, http.StatusNotFound, "user_not_found", "User not found")
		return
	}

	writeJSON(w, http.StatusOK, user)
}
