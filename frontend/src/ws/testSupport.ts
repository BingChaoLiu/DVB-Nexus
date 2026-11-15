// Test-support fake WebSocket (SessionStream tests only — never imported by
// production code). Implements the subset of the WebSocket surface the
// SessionStream state machine consumes, plus server-side helpers to drive
// the lifecycle deterministically.
export class FakeSocketHandle {
  readonly url: string;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onclose: ((event: { code: number; reason: string }) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;

  constructor(url: string) {
    this.url = url;
  }

  send(data: string) {
    this.sent.push(data);
  }

  close(_code?: number, _reason?: string) {
    this.onclose?.({ code: 1000, reason: "" });
  }

  // --- server-side drivers -------------------------------------------------

  serverAccept() {
    this.onopen?.();
  }

  serverMessage(frame: unknown) {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }

  serverRaw(text: string) {
    this.onmessage?.({ data: text });
  }

  serverClose(code: number, reason: string) {
    this.onclose?.({ code, reason });
  }
}
