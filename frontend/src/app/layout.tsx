import type { Metadata } from "next";
import { Bricolage_Grotesque, Outfit, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const bricolage = Bricolage_Grotesque({
  subsets: ["latin"],
  weight: ["800"],
  variable: "--font-display",
});

const outfit = Outfit({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-sans",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono",
});

import { AuthProvider } from "@/components/AuthContext";
import { AuthModal } from "@/components/AuthModal";

export const metadata: Metadata = {
  title: "DepExit — Exit Risky Dependencies with Proof",
  description:
    "Gemma 4 proposes dependency migrations. Docker proves them. Inspect risks, AST usage, patches, and baseline vs migrated test results in a verified Exit Capsule.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${bricolage.variable} ${outfit.variable} ${jetbrainsMono.variable} antialiased`}
    >
      <body className="min-h-screen text-ink flex flex-col selection:bg-butter selection:text-ink">
        <AuthProvider>
          {children}
          <AuthModal />
        </AuthProvider>
      </body>
    </html>
  );
}
