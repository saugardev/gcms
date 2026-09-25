import Workspace from "@/components/workspace";
import { currentUser } from "@/lib/session";

export default async function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const user = await currentUser();
  // Pages retain their session checks and exact login return paths.
  return <>{user && <Workspace user={user} />}{children}</>;
}
