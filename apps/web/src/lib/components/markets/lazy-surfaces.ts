let nativeModule: Promise<typeof import("./NativeMarkets.svelte")> | undefined;
let referenceModule: Promise<typeof import("./ReferenceMarkets.svelte")> | undefined;

// Share intent-prefetch and navigation requests. A failed prefetch must not poison navigation.
export function loadNativeMarkets() {
  return nativeModule ??= import("./NativeMarkets.svelte").catch((cause) => {
    nativeModule = undefined;
    throw cause;
  });
}

export function loadReferenceMarkets() {
  return referenceModule ??= import("./ReferenceMarkets.svelte").catch((cause) => {
    referenceModule = undefined;
    throw cause;
  });
}
