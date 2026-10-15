/// <reference types="vite/client" />

export {};

declare global {
  interface Window {
    __FREQID_CONFIG__?: {
      apiUrl?: string;
    };
  }
}
