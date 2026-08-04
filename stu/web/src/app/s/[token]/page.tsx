import { PublicShare } from "@/features/records/public-share";

export default async function SharedRecipePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <PublicShare token={token} />;
}
