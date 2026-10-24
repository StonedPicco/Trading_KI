"use client";

import { useEffect, useRef, useState } from "react";
import { wsUrl } from "./api";

export interface ServerEvent {
  id: number;
  type: "analysis.created" | "notification" | "bars.updated" | string;
  symbol: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

/** WebSocket subscription to the backend outbox with automatic reconnect (exponential backoff). */
export function useServerEvents(onEvent: (e: ServerEvent) => void): "connecting" | "open" | "closed" {
  const [state, setState] = useState<"connecting" | "open" | "closed">("connecting");
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry = 1000;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;

    const connect = () => {
      setState("connecting");
      ws = new WebSocket(wsUrl());
      ws.onopen = () => {
        retry = 1000;
        setState("open");
      };
      ws.onmessage = (msg) => {
        try {
          handler.current(JSON.parse(msg.data as string) as ServerEvent);
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = () => {
        setState("closed");
        if (!stopped) {
          timer = setTimeout(connect, retry);
          retry = Math.min(retry * 2, 30_000);
        }
      };
    };
    connect();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      ws?.close();
    };
  }, []);

  return state;
}
