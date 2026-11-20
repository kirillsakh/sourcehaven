import Link from "next/link";
import type { Metadata } from "next";
import type { ReactElement } from "react";

import styles from "@/app/page.module.css";

export const metadata: Metadata = {
  title: "Sourcehaven: questions about your documents",
  description:
    "Upload your PDFs and ask questions. Answers are generated from your documents and cite the pages they came from.",
};

export default function HomePage(): ReactElement {
  return (
    <main className={styles.page}>
      <h1 className={styles.wordmark}>
        Source<span className={styles.wordmarkTail}>haven</span>
      </h1>
      <p className={styles.lead}>
        Upload your PDFs, ask a question and get an answer that cites the pages it came from.
      </p>
      <Link className={styles.open} href="/app">
        Open the app
      </Link>
    </main>
  );
}
