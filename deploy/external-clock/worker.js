// Independent external clock trigger (reference implementation, NOT deployed, NOT active).
// It only dispatches the existing GitHub workflow `fpl-github-clock.yml`; occurrence identity,
// eligibility, de-duplication and provenance are decided GitHub-side by ops/external_clock_gate.py.
// No report logic, no schedule math, no retries beyond one bounded attempt, no secrets in this file.

const REPO = "iphoenk/FPL-iphoenk-engine";
const WORKFLOW = "fpl-github-clock.yml";
const TIMEOUT_MS = 10000;

export async function trigger(env, event, fetchImpl = fetch) {
  if (env.EXTERNAL_CLOCK_ENABLED !== "true") return { action: "DISABLED" };
  if (!env.GITHUB_TOKEN) return { action: "NO_CREDENTIAL" };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const response = await fetchImpl(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
      method: "POST",
      signal: controller.signal,
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "fpl-external-clock",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ref: "main",
        inputs: {
          trigger_origin: "EXTERNAL_INDEPENDENT_CLOCK",
          external_trigger_id: `${event.cron}@${new Date(event.scheduledTime).toISOString()}`,
        },
      }),
    });
    return { action: response.status === 204 ? "DISPATCHED" : "REJECTED", status: response.status };
  } catch (error) {
    return { action: "ERROR", error: error && error.name === "AbortError" ? "TIMEOUT" : "NETWORK" };
  } finally {
    clearTimeout(timer);
  }
}

export default {
  async scheduled(event, env, ctx) {
    const result = await trigger(env, event);
    console.log(JSON.stringify({ event: "FPL_EXTERNAL_CLOCK", cron: event.cron, ...result }));
  },
};
