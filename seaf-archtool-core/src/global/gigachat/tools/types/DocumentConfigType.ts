export type DocumentConfigType = {
  origin: string | Record<string, string> | undefined;
  params: Record<string, string>;
  profile: {
    base: string
  }
};
