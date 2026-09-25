import { redirect } from "next/navigation";
import { currentUser } from "@/lib/session";

export default async function AcceptedPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const user = await currentUser();
  if (!user) {
    const query = new URLSearchParams();
    for (const key of ["analysis", "peak", "candidate"]) if (typeof params[key] === "string") query.set(key, params[key]);
    redirect(`/login?return_to=${encodeURIComponent(query.size ? `/accepted?${query}` : "/accepted")}`);
  }
  return null;
}
