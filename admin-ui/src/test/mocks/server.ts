// Copyright 2026 FreqID Authors. Apache-2.0 License.
import { setupServer } from "msw/node";
import { handlers } from "./handlers";

export const server = setupServer(...handlers);
