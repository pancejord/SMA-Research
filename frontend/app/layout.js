// File purpose: Define the dashboard's shared page shell and metadata.
import "./globals.css";

export const metadata = {
  title: "SMA Research · Rankings",
  description: "Outfit rankings by ticker, timeframe, and completed trading sessions.",
};

// Wrap every dashboard page in the shared document structure.
export default function RootLayout({ children }) {
  return <html lang="en"><body>{children}</body></html>;
}
