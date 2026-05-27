import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        gain: {
          DEFAULT: "#16a34a",
          light: "#bbf7d0",
          dark: "#14532d",
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
