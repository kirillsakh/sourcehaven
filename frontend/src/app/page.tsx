import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Sourcehaven: questions about your documents",
  description:
    "Upload your PDFs and ask questions. Answers are generated from your documents and cite the pages they came from.",
};

export default function HomePage() {
  return (
    <main className="shell">
      <h1>Sourcehaven</h1>
      <p>Upload your PDFs, ask a question and get an answer that cites the pages it came from.</p>
      <p>
        <Link href="/app">Open the app</Link>
      </p>
    </main>
  );
}
