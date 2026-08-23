export const productConfig = {
  productName: process.env.NEXT_PUBLIC_PRODUCT_NAME || "Veritech Site Checker",
  parentBrand: process.env.NEXT_PUBLIC_PARENT_BRAND || "Veritech Diligence",
  marketingSiteUrl: process.env.NEXT_PUBLIC_MARKETING_SITE_URL || "https://veritechdiligence.com",
  appUrl: process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3000",
  reportName: "Technical Acquisition Brief",
  // Falls back to the literal ID because NEXT_PUBLIC_* vars are inlined at
  // Docker build time, not read at container runtime — the Dockerfile has
  // no build-arg wiring for this, so an unset env here always compiles to
  // "" in the deployed bundle regardless of any Fly runtime secret. Not a
  // secret itself (every NEXT_PUBLIC_* value ships visibly in the bundle
  // anyway), so a literal default is safe.
  gtmId: process.env.NEXT_PUBLIC_GTM_ID || "GTM-W38TRCSH",
};
