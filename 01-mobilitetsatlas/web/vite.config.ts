import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  // .env ligger i prosjektroten; ENTUR_CLIENT_NAME brukes til live-avganger i nettleseren
  envDir: "../../",
  envPrefix: ["VITE_", "ENTUR_"],
  server: {
    port: 5173,
    strictPort: true,
    // Prosjektroten: node_modules (MapLibre-workeren hentes direkte) og METODE.md i produktmappen
    fs: { allow: ["../.."] },
  },
});
