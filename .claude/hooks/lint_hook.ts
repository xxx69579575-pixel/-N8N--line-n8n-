#!/usr/bin/env node
/**
 * Claude Code PreToolUse Hook: Lint Check Before Git Commit
 * Runs ESLint before allowing git commit to ensure code quality
 */

import { appendFileSync, existsSync } from 'fs';
import { join } from 'path';
import { execSync } from 'child_process';

interface ToolInput {
  command?: string;
  [key: string]: unknown;
}

interface PreToolUseInput {
  session_id?: string;
  hook_event_name?: string;
  tool_name?: string;
  tool_input?: ToolInput;
  cwd?: string;
  [key: string]: unknown;
}

interface HookResponse {
  decision?: 'block' | 'approve';
  reason?: string;
}

function logDebug(message: string): void {
  const logPath = '.claude/hooks/lint_hook_debug.log';
  const timestamp = new Date().toISOString();
  const logEntry = `[${timestamp}] ${message}\n`;
  appendFileSync(logPath, logEntry);
}

function runLint(cwd: string): { success: boolean; output: string } {
  try {
    logDebug(`Running lint in: ${cwd}`);
    const output = execSync('npm run lint', {
      cwd,
      stdio: 'pipe',
      encoding: 'utf8',
      timeout: 30000
    });
    logDebug(`Lint passed: ${output}`);
    return { success: true, output };
  } catch (error: unknown) {
    const err = error as { stdout?: string; stderr?: string };
    const output = err.stdout || err.stderr || String(error);
    logDebug(`Lint failed: ${output}`);
    return { success: false, output };
  }
}

function main(): void {
  try {
    logDebug('=== LINT HOOK STARTED ===');

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
        const input: PreToolUseInput = JSON.parse(inputData);
        logDebug(`Lint hook input received: ${JSON.stringify(input, null, 2)}`);

        const toolName = input.tool_name || '';
        const toolInput = input.tool_input || {};
        const command = toolInput.command || '';
        const cwd = input.cwd || process.cwd();

        logDebug(`Tool name: ${toolName}`);
        logDebug(`Command: ${command}`);

        // Check if this is a git commit command
        const isGitCommit = command.includes('git commit');
        logDebug(`Is git commit: ${isGitCommit}`);

        if (isGitCommit) {
          // Skip lint if no package.json (non-JS/TS project)
          const pkgPath = join(cwd, 'package.json');
          if (!existsSync(pkgPath)) {
            logDebug('No package.json found - skipping lint check');
            console.log(JSON.stringify({}));
            logDebug('=== LINT HOOK COMPLETED (SKIPPED - no package.json) ===');
            return;
          }

          logDebug('Git commit detected - running lint check...');
          const { success, output } = runLint(cwd);

          if (!success) {
            logDebug('Lint failed - blocking git commit');
            const response: HookResponse = {
              decision: 'block',
              reason: `Lint check failed. Please fix the following issues before committing:\n\n${output}`
            };
            console.log(JSON.stringify(response));
            logDebug('=== LINT HOOK COMPLETED (BLOCKED) ===');
            return;
          }

          logDebug('Lint passed - allowing git commit');
        }

        // Allow the tool use
        console.log(JSON.stringify({}));
        logDebug('=== LINT HOOK COMPLETED (ALLOWED) ===');

      } catch (parseError) {
        logDebug(`Lint hook parse error: ${parseError}`);
        console.log(JSON.stringify({}));
        logDebug('=== LINT HOOK COMPLETED (PARSE ERROR) ===');
      }
    });

  } catch (error) {
    logDebug(`Lint hook error: ${error}`);
    console.log(JSON.stringify({}));
    logDebug('=== LINT HOOK COMPLETED (ERROR) ===');
  }
}

main();
