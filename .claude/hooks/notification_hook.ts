#!/usr/bin/env node
/**
 * Claude Code Notification Hook: Sound Alert for User Decisions
 * Plays a sound when Claude Code is waiting for user decisions (like allowing Bash commands)
 */

import { appendFileSync } from 'fs';
import { execSync } from 'child_process';

interface NotificationHookInput {
  notification_type: string;
  message?: string;
  [key: string]: unknown;
}

interface HookResponse {
  permissionDecision: 'allow';
  systemMessage?: string;
}

function logDebug(message: string): void {
  const logPath = '.claude/hooks/notification_hook_debug.log';
  const timestamp = new Date().toISOString();
  const logEntry = `[${timestamp}] ${message}\n`;
  appendFileSync(logPath, logEntry);
}

function playNotificationSound(soundFile: string): boolean {
  try {
    logDebug(`Playing notification sound: ${soundFile}`);
    execSync(`powershell -c "Add-Type -AssemblyName PresentationCore; $mp = New-Object System.Windows.Media.MediaPlayer; $mp.Open([uri]'${soundFile.replace(/\\/g, '/')}'); $mp.Play(); Start-Sleep 4"`, {
      stdio: 'pipe',
      timeout: 10000
    });
    logDebug('Notification sound played successfully');
    return true;
  } catch (error) {
    logDebug(`Failed to play notification sound: ${error}`);
    return false;
  }
}

function parseArgs(): { reminderFile: string } {
  const args = process.argv.slice(2);
  const idx = args.indexOf('--sound_effect_file');
  const reminderFile = idx !== -1 && args[idx + 1]
    ? args[idx + 1]
    : '.claude/hooks/default-notification-hook-reminder.mp3';
  return { reminderFile };
}

function main(): void {
  try {
    logDebug('=== NOTIFICATION HOOK STARTED ===');
    const { reminderFile } = parseArgs();

    // Read input from stdin
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
        const input: NotificationHookInput = JSON.parse(inputData);
        logDebug(`Notification hook input received: ${JSON.stringify(input, null, 2)}`);

        const notificationType = input.notification_type || '';
        const message = input.message || '';

        logDebug(`Notification type: ${notificationType}`);
        logDebug(`Message: ${message}`);

        const soundFile = reminderFile;

        // Play sound for all notifications (user decisions, permissions, etc.)
        const soundPlayed = playNotificationSound(soundFile);

        const response: HookResponse = {
          permissionDecision: 'allow',
          systemMessage: soundPlayed
            ? '🔔 Notification sound played'
            : '🔇 Failed to play notification sound'
        };

        // Output the response as JSON
        console.log(JSON.stringify(response));
        logDebug('=== NOTIFICATION HOOK COMPLETED ===');

      } catch (parseError) {
        const errorMsg = `Notification hook parse error: ${parseError}`;
        logDebug(errorMsg);

        // Always allow on parse error
        console.log(JSON.stringify({
          permissionDecision: 'allow',
          systemMessage: `Notification hook error: ${parseError}`
        }));
        logDebug('=== NOTIFICATION HOOK COMPLETED (PARSE ERROR) ===');
      }
    });

  } catch (error) {
    const errorMsg = `Notification hook error: ${error}`;
    logDebug(errorMsg);

    // Always allow on error
    console.log(JSON.stringify({
      permissionDecision: 'allow',
      systemMessage: `Notification hook error: ${error}`
    }));
    logDebug('=== NOTIFICATION HOOK COMPLETED (ERROR) ===');
  }
}

main();
