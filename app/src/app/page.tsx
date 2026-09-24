import Workspace from "@/components/workspace";
import { redirect } from "next/navigation";
import { currentUser } from "@/lib/session";
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const user = await currentUser();
  if (!user) {
    const query = new URLSearchParams();
    for (const key of ["analysis", "peak", "candidate"]) if (typeof params[key] === "string") query.set(key, params[key]);
    redirect(`/login?return_to=${encodeURIComponent(query.size ? `/?${query}` : "/")}`);
  }
  return <Workspace key={JSON.stringify([params.analysis, params.peak, params.candidate])} user={user} />;
}
