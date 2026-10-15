import React from "react";

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
  className?: string;
  pastel?: "lavender" | "butter" | "mint" | "sky" | "coral" | "cream-yellow";
}

export function Card({ children, className = "", pastel, ...props }: CardProps) {
  const pastelBg = pastel
    ? {
        lavender: "bg-[#C3B1F5]",
        butter: "bg-[#F9D56E]",
        mint: "bg-[#B9E4A1]",
        sky: "bg-[#A8CCF4]",
        coral: "bg-[#F2A58B]",
        "cream-yellow": "bg-[#FDF1D0]",
      }[pastel]
    : "bg-white";

  return (
    <div
      className={`border-[3px] border-[#17151F] rounded-[28px] shadow-[6px_6px_0_0_#17151F] p-6 transition-all duration-150 ${pastelBg} ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}

export interface FeatureCardProps extends React.HTMLAttributes<HTMLDivElement> {
  pillLabel?: string;
  title: string;
  subtitle?: string;
  pastel: "lavender" | "butter" | "mint" | "sky" | "coral";
  children?: React.ReactNode;
  className?: string;
}

export function FeatureCard({
  pillLabel,
  title,
  subtitle,
  pastel,
  children,
  className = "",
  ...props
}: FeatureCardProps) {
  const pastelBg = {
    lavender: "bg-[#C3B1F5]",
    butter: "bg-[#F9D56E]",
    mint: "bg-[#B9E4A1]",
    sky: "bg-[#A8CCF4]",
    coral: "bg-[#F2A58B]",
  }[pastel];

  return (
    <div
      className={`border-[3px] border-[#17151F] rounded-[28px] shadow-[6px_6px_0_0_#17151F] p-6 flex flex-col justify-between ${pastelBg} ${className}`}
      {...props}
    >
      <div>
        {pillLabel && (
          <span className="inline-block bg-white text-[#17151F] text-xs font-bold px-3 py-1 rounded-full shadow-[0_2px_4px_rgba(23,21,31,0.1)] mb-3">
            {pillLabel}
          </span>
        )}
        <h3 className="font-display text-2xl font-extrabold text-[#17151F] leading-tight mb-1">
          {title}
        </h3>
        {subtitle && (
          <p className="text-sm text-[#17151F]/80 font-medium">{subtitle}</p>
        )}
      </div>
      {children && <div className="mt-4">{children}</div>}
    </div>
  );
}

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary";
  children: React.ReactNode;
  icon?: React.ReactNode;
}

export function Button({
  variant = "primary",
  children,
  icon,
  className = "",
  disabled,
  ...props
}: ButtonProps) {
  if (variant === "secondary") {
    return (
      <button
        disabled={disabled}
        className={`bg-white text-[#17151F] border-[3px] border-[#17151F] rounded-full px-5 py-2.5 font-semibold shadow-[0_4px_0_0_#17151F] transition duration-150 inline-flex items-center justify-center gap-2 cursor-pointer hover:-translate-x-[2px] hover:-translate-y-[2px] hover:shadow-[0_6px_0_0_#17151F] active:translate-x-[2px] active:translate-y-[2px] active:shadow-[0_2px_0_0_#17151F] disabled:opacity-50 disabled:cursor-not-allowed ${className}`}
        {...props}
      >
        {icon}
        {children}
      </button>
    );
  }

  return (
    <button
      disabled={disabled}
      className={`bg-[#17151F] text-white rounded-full px-6 py-3 font-semibold shadow-[0_4px_0_0_#6E56D9] transition duration-150 inline-flex items-center justify-center gap-2 cursor-pointer hover:-translate-x-[2px] hover:-translate-y-[2px] hover:shadow-[0_6px_0_0_#6E56D9] active:translate-x-[2px] active:translate-y-[2px] active:shadow-[0_2px_0_0_#6E56D9] disabled:opacity-50 disabled:cursor-not-allowed ${className}`}
      {...props}
    >
      {icon}
      {children}
    </button>
  );
}

export function CodeChip({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={`font-mono text-xs bg-white text-[#17151F] border border-[#17151F]/20 rounded-full px-2.5 py-1 shadow-[0_1px_3px_rgba(23,21,31,0.08)] inline-flex items-center gap-1 ${className}`}
    >
      {children}
    </span>
  );
}

export function Sticker({
  children,
  variant = "butter",
  className = "",
}: {
  children: React.ReactNode;
  variant?: "butter" | "sky" | "mint" | "coral";
  className?: string;
}) {
  const bg = {
    butter: "bg-[#F9D56E]",
    sky: "bg-[#A8CCF4]",
    mint: "bg-[#B9E4A1]",
    coral: "bg-[#F2A58B]",
  }[variant];

  return (
    <div
      className={`inline-flex items-center justify-center font-display font-extrabold text-sm md:text-base tracking-wider uppercase px-4 py-1.5 border-[3px] border-[#17151F] shadow-[3px_3px_0_0_#17151F] rounded-xl transform -rotate-6 select-none ${bg} ${className}`}
    >
      {children}
    </div>
  );
}

export function NoticeBanner({
  title,
  children,
  code,
  note,
  className = "",
}: {
  title?: string;
  children: React.ReactNode;
  code?: string;
  note?: string;
  className?: string;
}) {
  return (
    <div
      className={`bg-[#FDF1D0] rounded-[28px] p-5 shadow-[0_6px_14px_rgba(23,21,31,0.06)] flex flex-col md:flex-row md:items-center justify-between gap-3 text-sm text-[#17151F] ${className}`}
    >
      <div className="flex items-start gap-3">
        <span className="text-xl">⚠️</span>
        <div>
          {title && <span className="font-bold mr-2">{title}:</span>}
          <div className="inline">{children}</div>
          {code && <CodeChip className="ml-2 bg-white/90">{code}</CodeChip>}
        </div>
      </div>
      {note && (
        <span className="text-xs text-[#5A5870] font-medium whitespace-nowrap self-end md:self-center">
          {note}
        </span>
      )}
    </div>
  );
}
