"use strict";

import * as vscode from 'vscode';
import { WorkspaceFolder, DebugConfiguration, ProviderResult } from 'vscode';

export function activate(context: vscode.ExtensionContext) {

	console.log('Starting ansibug extension');

	context.subscriptions.push(
		vscode.commands.registerCommand('extension.ansibug.runEditorContents', (resource: vscode.Uri) => {
			let targetResource = resource;
			if (!targetResource && vscode.window.activeTextEditor) {
				targetResource = vscode.window.activeTextEditor.document.uri;
			}
			if (targetResource) {
				vscode.debug.startDebugging(undefined, {
						type: 'ansibug',
						name: 'Run File',
						request: 'launch',
						playbook: targetResource.fsPath
					},
					{ noDebug: true }
				);
			}
		}),
		vscode.commands.registerCommand('extension.ansibug.debugEditorContents', (resource: vscode.Uri) => {
			let targetResource = resource;
			if (!targetResource && vscode.window.activeTextEditor) {
				targetResource = vscode.window.activeTextEditor.document.uri;
			}
			if (targetResource) {
				vscode.debug.startDebugging(undefined, {
					type: 'ansibug',
					name: 'Debug File',
					request: 'launch',
					playbook: targetResource.fsPath
				});
			}
		}),
	);

	context.subscriptions.push(vscode.commands.registerCommand('ansibug.getPlaybook', config => {
		return vscode.window.showInputBox({
			placeHolder: "Please enter the name of a playbook to debug",
			value: "main.yml"
		});
	}));

	// register a configuration provider for 'mock' debug type
	//const provider = new MockConfigurationProvider();
	//context.subscriptions.push(vscode.debug.registerDebugConfigurationProvider('ansibug', provider));

	// register a dynamic configuration provider for 'mock' debug type
	context.subscriptions.push(vscode.debug.registerDebugConfigurationProvider('ansibug', {
		provideDebugConfigurations(folder: WorkspaceFolder | undefined): ProviderResult<DebugConfiguration[]> {
			return [
				{
					name: "Dynamic Launch",
					request: "launch",
					type: "ansibug",
					playbook: "${file}"
				},
				{
					name: "Another Dynamic Launch",
					request: "launch",
					type: "ansibug",
					playbook: "${file}"
				},
				{
					name: "Mock Launch",
					request: "launch",
					type: "ansibug",
					playbook: "${file}"
				}
			];
		},
	}, vscode.DebugConfigurationProviderTriggerKind.Dynamic));

	context.subscriptions.push(vscode.debug.registerDebugAdapterTrackerFactory('ansibug', {
		createDebugAdapterTracker: (session: vscode.DebugSession): ProviderResult<vscode.DebugAdapterTracker> => {
			return new MyDebugTracker();
		}
	}));

	context.subscriptions.push(vscode.debug.registerDebugAdapterDescriptorFactory('ansibug', {
		createDebugAdapterDescriptor: (session: vscode.DebugSession) => {
			return new vscode.DebugAdapterServer(6845);
		}
	}));
}

export function deactivate() {}

class MyDebugTracker implements vscode.DebugAdapterTracker {

	onWillStartSession?(): void {
		console.log("Debug Start");
	}

	/**
	 * The debug adapter is about to receive a Debug Adapter Protocol message from VS Code.
	 */
	onWillReceiveMessage?(message: any): void {
		console.log('Debug ToAdapter: ', JSON.stringify(message));
	}
	/**
	 * The debug adapter has sent a Debug Adapter Protocol message to VS Code.
	 */
	onDidSendMessage?(message: any): void {
		console.log('Debug FromAdapter: ', JSON.stringify(message));
	}
	/**
	 * The debug adapter session is about to be stopped.
	 */
	onWillStopSession?(): void {
		console.log("Debug Stop");
	}
	/**
	 * An error with the debug adapter has occurred.
	 */
	onError?(error: Error): void {
		console.log("Debug Error: ", error.message, error.stack);
	}
	/**
	 * The debug adapter has exited with the given exit code or signal.
	 */
	onExit?(code: number | undefined, signal: string | undefined): void {
		console.log("Debug Exit");
	}
}
