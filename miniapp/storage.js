// The pages' files in the bucket (DESIGN_miniapp_storage.md §5, §7): the page key, the names,
// the download and the decryption, word for word as `stamind/page_files/recipe.py` does
// them. Shared by the calendar and "Goals & plan". The key and what the files hold stay in
// memory: this code writes nothing to the browser's storage (Telegram's script does, §5).
import { VERSION, base64urlBytes, inflate } from "./calendar_logic.js?v=dev";

// Word for word the labels in `stamind/page_files/sync.py`; a Python test holds them together.
export const INDEX = "calendar/index";
export const PLAN = "plan";

// How long a download may take before the file counts as missing (§7.1). A first guess.
const FETCH_MS = 10000;

const encoder = new TextEncoder();

function param(hash, name) {
  const match = new RegExp(`(?:^|[#&])${name}=([^&]+)`).exec(hash || "");
  return match ? decodeURIComponent(match[1]) : null;
}

export function storageFromHash(hash) {
  // The page key, the bucket and the folder the button carries; null without them (§8).
  const key = param(hash, "k");
  const bucket = param(hash, "b");
  const folder = param(hash, "f");
  if (!key || !bucket || !folder) {
    return null;
  }
  return { key: base64urlBytes(key), bucket, folder };
}

async function hkdf(secret, label, length) {
  const base = await crypto.subtle.importKey("raw", secret, "HKDF", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "HKDF", hash: "SHA-256", salt: new Uint8Array(), info: encoder.encode(label) },
    base, length * 8,
  );
  return new Uint8Array(bits);
}

export async function fileName(pageKey, label) {
  const bytes = await hkdf(pageKey, `name:${label}`, 16);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function fileUrl(storage, name) {
  // The address Google answers a page from another site on (§5).
  const object = encodeURIComponent(`${storage.folder}/${name}`);
  return `https://storage.googleapis.com/storage/v1/b/${storage.bucket}/o/${object}?alt=media`;
}

export async function unseal(pageKey, blob) {
  // 12 bytes, then the JSON compressed and encrypted with AES-GCM (§5).
  const raw = await hkdf(pageKey, "file-key", 32);
  const key = await crypto.subtle.importKey("raw", raw, "AES-GCM", false, ["decrypt"]);
  const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: blob.slice(0, 12) }, key,
                                            blob.slice(12));
  return JSON.parse(await inflate(new Uint8Array(plain)));
}

export async function fetchFile(storage, label) {
  // A file that cannot be downloaded, decrypted, or that says another version, throws: the
  // page counts it as missing (§7.1).
  const url = fileUrl(storage, await fileName(storage.key, label));
  const response = await fetch(url, { cache: "no-store", signal: AbortSignal.timeout(FETCH_MS) });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  const content = await unseal(storage.key, new Uint8Array(await response.arrayBuffer()));
  if (content.v !== VERSION) {
    throw new Error(`The file says version ${content.v}, and this page reads ${VERSION}.`);
  }
  return content;
}
