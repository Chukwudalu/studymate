export function statusPillClass(status: string): string {
  if (status === "done") return "pill pill-done";
  if (status === "failed") return "pill pill-failed";
  return "pill pill-progress";
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}
