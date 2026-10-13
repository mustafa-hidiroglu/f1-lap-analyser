import type { Metadata } from "next";
import { Analyser } from "@/components/analyse/Analyser";

export const metadata: Metadata = {
  title: "Analyser",
  description: "Compare two Formula 1 laps: delta, synced traces, track map, corner phases and lap rating.",
};

export default function AnalysePage() {
  return <Analyser />;
}
