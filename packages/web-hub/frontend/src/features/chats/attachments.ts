import type { ChatAttachment } from "@/api/contracts";

const maximumAttachments = 5;

function readFile(file: File): Promise<ChatAttachment> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(`${file.name || "Bild"} konnte nicht gelesen werden.`));
    reader.onload = () => resolve({
      name: file.name || `image_${Date.now()}.png`,
      type: file.type || "image/png",
      data: String(reader.result ?? ""),
    });
    reader.readAsDataURL(file);
  });
}

export async function appendImageFiles(
  current: ChatAttachment[],
  files: FileList | File[],
) {
  const images = Array.from(files).filter((file) => file.type.startsWith("image/"));
  if (current.length + images.length > maximumAttachments) {
    throw new Error(`Maximal ${maximumAttachments} Bilder sind pro Nachricht möglich.`);
  }
  return [...current, ...(await Promise.all(images.map(readFile)))];
}
