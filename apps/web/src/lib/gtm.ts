declare global {
  interface Window {
    dataLayer?: unknown[];
  }
}

export function gtmPush(data: Record<string, unknown>) {
  window.dataLayer = window.dataLayer || [];
  window.dataLayer.push(data);
}
