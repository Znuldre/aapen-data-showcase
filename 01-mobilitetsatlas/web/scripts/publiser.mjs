// Publiserer atlaset på GitHub Pages: bygger appen med dataene fra steg 6 og erstatter grenen
// gh-pages i origin med resultatet. Dataene (≈ 190 MB) ligger ikke i main og kan ikke lages i CI,
// fordi reisetidene tar et døgn å beregne. Nettstedet bygges derfor lokalt, og grenen har bare én
// commit, slik at gamle versjoner av dataene ikke hoper seg opp i historikken.
//
// Kjøres fra prosjektroten:  npm run publiser:atlas

import { execSync } from "node:child_process";
import { existsSync, rmSync, writeFileSync } from "node:fs";

const kjør = (cmd, cwd) => execSync(cmd, { cwd, stdio: "inherit" });
const les = (cmd) => execSync(cmd).toString().trim();

const remote = les("git remote get-url origin");
const [, eier, repo] = remote.match(/github\.com[:/]([^/]+)\/([^/]+?)(?:\.git)?$/) ?? [];
if (!repo) throw new Error(`origin peker ikke på et GitHub-repo: ${remote}`);
if (!existsSync("public/data/meta.json")) throw new Error("Mangler public/data. Kjør pipelinen til og med steg 6 først.");

rmSync("dist", { recursive: true, force: true }); // ingen rester fra tidligere bygg i det som publiseres
kjør(`npm run build -- --base=/${repo}/`);
writeFileSync("dist/.nojekyll", ""); // Pages skal servere filene som de er, uten Jekyll

// Samme navn og e-post som commit-ene i hovedrepoet
const ident = ["user.name", "user.email"].map((k) => `-c ${k}="${les(`git config ${k}`)}"`).join(" ");
rmSync("dist/.git", { recursive: true, force: true });
kjør("git init -q -b gh-pages", "dist");
kjør("git config core.autocrlf false", "dist");
kjør("git add -A", "dist");
kjør(`git ${ident} commit -q -m "Publiser mobilitetsatlaset"`, "dist");
kjør(`git push -q -f ${remote} gh-pages`, "dist");
rmSync("dist/.git", { recursive: true, force: true });

console.log(`Publisert. GitHub Pages oppdaterer https://${eier.toLowerCase()}.github.io/${repo}/ i løpet av et par minutter.`);
