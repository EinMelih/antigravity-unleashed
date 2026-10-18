/**
 * Antigravity Frontend - ConnectRPC & Protobuf Service Definitions
 * Decoded from FileDescriptorProto definitions in main_root.formatted.js
 */

export const CONNECT_SERVICES = {
  LanguageServerService: {
    package: "exa.language_server_pb",
    service: "LanguageServerService",
    methods: [
      "GetStatus",
      "GetUserStatus",
      "GetAvailableModels",
      "RetrieveUserQuotaSummary",
      "GetCascadeTrajectory",
      "StartCascade",
      "CancelCascade",
      "HandleCascadeUserInteraction",
      "GetConversationHistory",
      "DeleteConversation",
      "ArchiveConversation",
    ],
  },
  ExtensionServerService: {
    package: "exa.extension_server_pb",
    service: "ExtensionServerService",
    methods: [
      "LanguageServerStarted",
      "OpenSetting",
      "OpenFilePointer",
      "InsertCodeAtCursor",
      "LogEvent",
      "ExecuteCommand",
      "ShowTerminal",
      "SendTerminalInput",
      "TerminateCommand",
      "GetLintErrors",
      "OpenDiffZones",
      "StartAudioRecording",
      "EndAudioRecording",
    ],
  },
  HostBridgeService: {
    package: "exa.host_bridge_pb",
    service: "HostBridgeService",
    methods: ["GetUpdateStatus", "ApplyUpdate"],
  },
};
