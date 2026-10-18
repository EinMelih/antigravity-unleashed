/**
 * Antigravity Frontend - Feature Flags & Entitlements Module
 * Extracted and deobfuscated from main_root.formatted.js (lines ~15655-15670, ~41750-41765)
 *
 * This module encapsulates the Google Mendel A/B experiment evaluation,
 * user cohort and tier entitlements, and capability configuration resolution.
 */

// User Tier Enums (from state & quota schemas)
export const USER_TIERS = {
  USER_TIER_UNSPECIFIED: { value: 0, description: "Unspecified user tier" },
  USER_TIER_FREE: {
    value: 1,
    description: "Standard free tier with default 5-hour quota window",
  },
  USER_TIER_PRO: {
    value: 2,
    description: "Pro tier with elevated quotas and priority model access",
  },
  USER_TIER_ENTERPRISE: {
    value: 3,
    description:
      "Enterprise tier with GCP Project billing and custom compliance",
  },
};

// Mendel Experiments Registry (lines 41750-41765)
export const MENDEL_EXPERIMENTS = [
  {
    key: "enable-browser-subagent-v2",
    type: "boolean",
    default: false,
    description: "Activates the headless Chrome DevTools subagent automation",
  },
  {
    key: "enable-gemini-next-opt-out-switch",
    type: "boolean",
    default: false,
    description:
      "Exposes settings toggle to opt out of Gemini Next experimental weights",
  },
  {
    key: "enable-jetbox-gcert",
    type: "boolean",
    default: false,
    description:
      "Enforces Google internal gcert authentication for internal clusters",
  },
  {
    key: "enable-jetski-chat",
    type: "boolean",
    default: true,
    description:
      "Core feature flag controlling the Jetski agentic conversation engine",
  },
  {
    key: "enable-thumbs-down-reroll",
    type: "boolean",
    default: false,
    description:
      "Allows regenerating step trajectories following negative feedback",
  },
  {
    key: "jetbox-usage-tips",
    type: "json",
    default: [],
    description: "Contextual tips list injected into empty agent chat states",
  },
  {
    key: "max-best-of-n",
    type: "integer",
    default: 8,
    description: "Maximum candidate sampling width for plan/action exploration",
  },
  {
    key: "remote-control-setting-enabled",
    type: "boolean",
    default: false,
    description: "Exposes remote control and API bridge toggles in settings",
  },
];

// Feature Cohort Evaluator (lines 15666-15670)
export function isFeatureGated(feature, env) {
  // User cohort check (google internal vs external)
  if (feature.userCohortGating && feature.userCohortGating !== "all") {
    if (feature.userCohortGating === "google" && !env.isGoogleInternal)
      return true;
    if (feature.userCohortGating === "external" && env.isGoogleInternal)
      return true;
  }
  // Build environment check (desktop vs web vs cider)
  if (feature.buildEnvGating && !feature.buildEnvGating.includes("all")) {
    if (!feature.buildEnvGating.includes(env.environment)) return true;
  }
  // Screen size check (narrow mobile vs wide desktop)
  if (feature.runtimeGating && feature.runtimeGating.supportedScreenSizes) {
    const currentSize = env.isNarrowLayout ? "narrow" : "wide";
    if (
      !feature.runtimeGating.supportedScreenSizes.includes("all") &&
      !feature.runtimeGating.supportedScreenSizes.includes(currentSize)
    ) {
      return true;
    }
  }
  return false;
}
