import { redirect } from "next/navigation";
import { AuthForm } from "@/components/auth-form";
import { currentUser } from "@/lib/session";
import { safeReturnTo } from "@/lib/auth-path";
export default async function Login({ searchParams }: { searchParams: Promise<{ return_to?: string }> }) {
  const returnTo = safeReturnTo((await searchParams).return_to);
  if (await currentUser()) redirect(returnTo);
  return <AuthForm returnTo={returnTo} />;
}
