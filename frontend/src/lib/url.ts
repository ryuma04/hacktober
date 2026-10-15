export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";
export const IS_MOCK = process.env.NEXT_PUBLIC_MOCK === "1";

export const apiUrl = (u: string): string => {
  if (!u) return "";
  if (/^https?:\/\//.test(u)) return u;

  if (IS_MOCK) {
    if (u.endsWith("/capsule.md")) return "/fixtures/capsule.md";
    if (u.endsWith("/patch.diff")) return "/fixtures/patch.diff";
    if (u.endsWith("/capsule")) return "/fixtures/capsule.json";
    
    // Log URL mapping: /api/analyses/{id}/runs/{run}/log?stream=install|test
    const logMatch = u.match(/runs\/([^/]+)\/log\?stream=([^&]+)/);
    if (logMatch) {
      const [, run, stream] = logMatch;
      return `/fixtures/logs/${run}-${stream}.log`;
    }
  }

  return `${API}${u.startsWith("/") ? u : `/${u}`}`;
};
