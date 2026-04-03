#!/usr/bin/env node
/**
 * Claude Code PostToolUse Hook: Run Tests After File Edits
 * Runs tests after Edit/Write operations and warns if they fail
 */

import { appendFileSync, existsSync, readFileSync } from 'fs';
import { execSync } from 'child_process';
import { join } from 'path';

interface PostToolUseInput {
  session_id?: string;
  hook_event_name?: string;
  tool_name?: string;
  tool_input?: Record<string, unknown>;
  tool_response?: Record<string, unknown>;
  cwd?: string;
  [key: string]: unknown;
}

interface HookResponse {
  continue?: boolean;
  systemMessage?: string;
}

interface TestSetup {
  hasTests: boolean;
  command: string;
  reason: string;
}

function logDebug(message: string): void {
  const logPath = '.claude/hooks/test_runner_hook_debug.log';
  const timestamp = new Date().toISOString();
  appendFileSync(logPath, `[${timestamp}] ${message}\n`);
}

function detectTestSetup(cwd: string): TestSetup {
  const pkgPath = join(cwd, 'package.json');
  if (existsSync(pkgPath)) {
    try {
      const pkg = JSON.parse(readFileSync(pkgPath, 'utf8'));
      const scripts: Record<string, string> = pkg.scripts || {};

      if (scripts['test']) {
        return { hasTests: true, command: 'npm test', reason: 'Found "test" script in package.json' };
      }
      if (scripts['test:unit']) {
        return { hasTests: true, command: 'npm run test:unit', reason: 'Found "test:unit" script in package.json' };
      }
    } catch {
      logDebug('Failed to parse package.json');
    }
  }

  const vitestConfigs = ['vitest.config.ts', 'vitest.config.js', 'vitest.config.mts'];
  for (const config of vitestConfigs) {
    if (existsSync(join(cwd, config))) {
      return { hasTests: true, command: 'npx vitest run', reason: `Found ${config}` };
    }
  }

  const jestConfigs = ['jest.config.ts', 'jest.config.js', 'jest.config.mjs'];
  for (const config of jestConfigs) {
    if (existsSync(join(cwd, config))) {
      return { hasTests: true, command: 'npx jest --passWithNoTests', reason: `Found ${config}` };
    }
  }

  return { hasTests: false, command: '', reason: 'No test setup detected' };
}

function runTests(command: string, cwd: string): { success: boolean; output: string } {
  try {
    logDebug(`Running tests with: ${command}`);
    const output = execSync(command, {
      cwd,
      stdio: 'pipe',
      encoding: 'utf8',
      timeout: 120000
    });
    logDebug(`Tests passed: ${output}`);
    return { success: true, output };
  } catch (error: unknown) {
    const err = error as { stdout?: string; stderr?: string };
    const output = err.stdout || err.stderr || String(error);
    logDebug(`Tests failed: ${output}`);
    return { success: false, output };
  }
}

function main(): void {
  try {
    logDebug('=== TEST RUNNER HOOK STARTED ===');

    let inputData = '';
    process.stdin.setEncoding('utf8');

    process.stdin.on('readable', () => {
      let chunk;
      while ((chunk = process.stdin.read()) !== null) {
        inputData += chunk;
      }
    });

    process.stdin.on('end', () => {
      try {
        const input: PostToolUseInput = JSON.parse(inputData);
        const cwd = input.cwd || process.cwd();

        logDebug(`Tool: ${input.tool_name}, CWD: ${cwd}`);

        const testSetup = detectTestSetup(cwd);
        logDebug(`Test setup: ${JSON.stringify(testSetup)}`);

        if (!testSetup.hasTests) {
          logDebug('No tests found - skipping');
          console.log(JSON.stringify({ continue: true }));
          logDebug('=== TEST RUNNER HOOK COMPLETED (NO TESTS) ===');
          return;
        }

        logDebug(`Running tests: ${testSetup.reason}`);
        const { success, output } = runTests(testSetup.command, cwd);

        if (!success) {
          logDebug('Tests failed');
          const response: HookResponse = {
            continue: true,
            systemMessage: `⚠️ Warning: Tests failed after this edit!\n\n${output}`
          };
          console.log(JSON.stringify(response));
          logDebug('=== TEST RUNNER HOOK COMPLETED (TESTS FAILED) ===');
          return;
        }

        logDebug('Tests passed');
        console.log(JSON.stringify({ continue: true }));
        logDebug('=== TEST RUNNER HOOK COMPLETED (TESTS PASSED) ===');

      } catch (parseError) {
        logDebug(`Parse error: ${parseError}`);
        console.log(JSON.stringify({ continue: true }));
        logDebug('=== TEST RUNNER HOOK COMPLETED (PARSE ERROR) ===');
      }
    });

  } catch (error) {
    logDebug(`Hook error: ${error}`);
    console.log(JSON.stringify({ continue: true }));
    logDebug('=== TEST RUNNER HOOK COMPLETED (ERROR) ===');
  }
}

main();
