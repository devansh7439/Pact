import type { Metadata } from "next";
import { IBM_Plex_Mono, Inter } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";

const sans = Inter({ subsets: ["latin"], variable: "--font-sans" });
const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "Pact · Payment Recovery Console",
  description: "Payment recovery for AI agents, on PayPal (PRP v0.1)",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`dark ${sans.variable} ${mono.variable}`} style={{ colorScheme: "dark" }}>
      <body className="min-h-screen bg-[#090909] font-sans text-[#e6edf3] antialiased selection:bg-[#2ebd7b]/30 selection:text-white">
        <div className="flex min-h-screen flex-col md:flex-row bg-[#090909]">
          <Sidebar />
          <main className="flex-1 min-w-0 overflow-y-auto px-4 py-6 sm:px-6 md:px-8 md:py-7 w-full max-w-[1400px]">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
