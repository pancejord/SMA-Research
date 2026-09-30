// File purpose: Keep Next.js build discovery scoped to the separate frontend folder.
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(fileURLToPath(import.meta.url));
export default { turbopack: { root } };
