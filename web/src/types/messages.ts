export type ObjectDetection = {
  label: string;
  confidence: number;
  bbox?: [number, number, number, number];
};

export type InferenceMessage = {
  timestamp: string;
  guidance_text?: string;
  scene_summary?: string;
  objects?: ObjectDetection[];
};

export function isInferenceMessage(value: unknown): value is InferenceMessage {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const candidate = value as Partial<InferenceMessage>;
  return typeof candidate.timestamp === "string";
}
