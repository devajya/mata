"use client";

import { useEffect, useState } from "react";
import { EdgeCalcStatus } from "../hooks/useEdgeCalculation";

const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

interface Props {
  status: EdgeCalcStatus;
}

/**
 * Bottom-right overlay showing async edge calculation progress.
 *
 * AGENT-CTX: Renders nothing when status is "ready" or "idle" — no visual clutter
 * when there is nothing to report. Only visible during the brief loading window
 * (~600ms for mocks, longer for real API) and on failure.
 *
 * AGENT-CTX: position:absolute places it inside React Flow's container,
 * anchored to the bottom-right corner regardless of canvas pan/zoom.
 * z-index 6 places it above the gap legend (5) but below drawers (40+).
 */
export function EdgeLoadingIndicator({ status }: Props) {
  const [frame, setFrame] = useState(0);

  useEffect(() => {
    if (status !== "loading") return;
    const id = setInterval(() => setFrame((f) => (f + 1) % SPINNER_FRAMES.length), 100);
    return () => clearInterval(id);
  }, [status]);

  if (status === "ready" || status === "idle") return null;

  return (
    <div
      style={{
        position:        "absolute",
        bottom:          40,
        right:           12,
        zIndex:          6,
        backgroundColor: "#fff",
        border:          "1px solid #e0e0e0",
        borderRadius:    6,
        padding:         "0.3rem 0.6rem",
        fontSize:        "0.75rem",
        color:           status === "failed" ? "#c00" : "#555",
        display:         "flex",
        alignItems:      "center",
        gap:             "0.35rem",
        boxShadow:       "0 1px 4px rgba(0,0,0,0.08)",
      }}
    >
      {status === "loading" ? (
        <>
          <span style={{ fontFamily: "monospace" }}>{SPINNER_FRAMES[frame]}</span>
          Calculating connections…
        </>
      ) : (
        <>
          <span>⚠</span>
          No usable connections found
        </>
      )}
    </div>
  );
}
