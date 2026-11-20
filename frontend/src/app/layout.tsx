import type { Metadata } from "next";
import type { ReactElement, ReactNode } from "react";

import "@fontsource-variable/atkinson-hyperlegible-next";
import "@fontsource-variable/source-serif-4";
import "@/app/globals.css";

export const metadata: Metadata = {
  title: { default: "Sourcehaven", template: "%s | Sourcehaven" },
  description: "Ask questions about your own documents and get answers with cited sources.",
};

export default function RootLayout({ children }: { children: ReactNode }): ReactElement {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
