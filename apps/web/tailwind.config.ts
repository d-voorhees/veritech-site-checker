import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        border: "#C9C9BD",
        background: "#FAFAF7",
        surface: "#FFFFFF",
        foreground: "#0A0A0A",
        muted: "#EFEBE0",
        "muted-foreground": "#44443C",
        primary: "#1F3A5F",
        "primary-foreground": "#FAFAF7",
        "primary-hover": "#132845",
      },
      borderRadius: {
        lg: "0px",
        md: "0px",
        sm: "0px",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
