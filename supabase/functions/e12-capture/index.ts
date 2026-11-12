import { handleE12Capture } from "./worker.ts";

Deno.serve((request) =>
  handleE12Capture(request, {
    env: (name) => Deno.env.get(name),
  })
);
