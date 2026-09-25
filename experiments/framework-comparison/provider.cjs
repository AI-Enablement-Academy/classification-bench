'use strict';
const fs = require('fs');
const path = require('path');
class SavedProvider {
  constructor(options) { this.config = options && options.config; }
  id() { return 'saved-fixture'; }
  async callApi(prompt, context) {
    const dir = process.env.SPIKE_FIXTURE_DIR;
    if (!dir) throw new Error('SPIKE_FIXTURE_DIR required');
    const responses = JSON.parse(fs.readFileSync(path.join(dir, 'responses.json'), 'utf8'));
    const requests = JSON.parse(fs.readFileSync(path.join(dir, 'requests.json'), 'utf8'));
    const caseId = context.vars.case_id;
    if (!Object.prototype.hasOwnProperty.call(requests, caseId)) throw new Error('unknown case');
    if (prompt !== requests[caseId].prompt) throw new Error('rendered prompt drift');
    const attemptFile = path.join(dir, 'promptfoo-attempts.jsonl');
    const count = fs.existsSync(attemptFile) ? fs.readFileSync(attemptFile, 'utf8').split('\n').filter(line => line && JSON.parse(line).case_id === caseId).length : 0;
    fs.appendFileSync(attemptFile, JSON.stringify({case_id: caseId, ordinal: count + 1, prompt_hex: Buffer.from(prompt, 'utf8').toString('hex'), context_keys: Object.keys(context).sort(), vars_keys: Object.keys(context.vars).sort(), request_identity: requests[caseId].identity_sha256}) + '\n');
    if (caseId === 'crash' && process.env.SPIKE_CRASH === '1') process.exit(77);
    if (caseId === 'rate_limit' && count === 0) return {error: 'simulated 429', metadata: {reported_model: responses[caseId].reported_model}};
    if (caseId === 'specialist') return {output: responses[caseId].native, metadata: {reported_model: responses[caseId].reported_model, native_method: 'choice-probability'}};
    return {output: responses[caseId].raw, metadata: {reported_model: responses[caseId].reported_model}};
  }
}
module.exports = SavedProvider;
