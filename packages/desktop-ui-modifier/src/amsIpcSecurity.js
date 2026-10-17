"use strict";

const path = require('path');

const TEMP_CONVERSATION_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

class TemporaryConversationRegistry {
    constructor(options = {}) {
        this.ttlMs = Number(options.ttlMs || 2 * 60 * 60 * 1000);
        this.now = typeof options.now === 'function' ? options.now : Date.now;
        this.entries = new Map();
        if (!Number.isFinite(this.ttlMs) || this.ttlMs <= 0) {
            throw new Error('Temporary conversation TTL must be positive.');
        }
    }

    normalize(value) {
        if (typeof value !== 'string' || !TEMP_CONVERSATION_ID_PATTERN.test(value)) {
            throw new Error('Temporary conversation ID is not a valid UUID.');
        }
        return value;
    }

    prune() {
        const now = this.now();
        for (const [conversationId, registeredAt] of this.entries) {
            if (now - registeredAt >= this.ttlMs) {
                this.entries.delete(conversationId);
            }
        }
    }

    register(value) {
        const conversationId = this.normalize(value);
        this.prune();
        this.entries.set(conversationId, this.now());
        return conversationId;
    }

    require(value) {
        const conversationId = this.normalize(value);
        this.prune();
        if (!this.entries.has(conversationId)) {
            throw new Error('Conversation is not registered as temporary in this app session.');
        }
        return conversationId;
    }

    delete(value) {
        return this.entries.delete(this.normalize(value));
    }
}

class OneShotPathLeaseRegistry {
    constructor(options = {}) {
        this.ttlMs = Number(options.ttlMs || 30_000);
        this.now = typeof options.now === 'function' ? options.now : Date.now;
        this.entries = new Map();
        if (!Number.isFinite(this.ttlMs) || this.ttlMs <= 0) {
            throw new Error('Workspace lease TTL must be positive.');
        }
    }

    issue(ownerId, workspacePath) {
        if ((typeof ownerId !== 'number' && typeof ownerId !== 'string') || ownerId === '') {
            throw new Error('Workspace lease owner is invalid.');
        }
        if (typeof workspacePath !== 'string' || !workspacePath.trim()) {
            throw new Error('Workspace lease path is invalid.');
        }
        this.entries.set(ownerId, {
            path: workspacePath,
            expiresAt: this.now() + this.ttlMs,
        });
        return workspacePath;
    }

    consume(ownerId) {
        const entry = this.entries.get(ownerId);
        this.entries.delete(ownerId);
        if (!entry || this.now() >= entry.expiresAt) return null;
        return entry.path;
    }

    delete(ownerId) {
        return this.entries.delete(ownerId);
    }
}

function normalizePathForComparison(value, options = {}) {
    const pathImpl = options.pathImpl || path;
    const platform = options.platform || process.platform;
    if (typeof value !== 'string' || !value.trim()) return '';
    const normalized = pathImpl.normalize(pathImpl.resolve(value));
    return platform === 'win32' ? normalized.toLocaleLowerCase('en-US') : normalized;
}

function isRegisteredProjectPath(projects, targetPath, options = {}) {
    if (!Array.isArray(projects)) return false;
    const realpath = typeof options.realpath === 'function' ? options.realpath : (value) => value;
    let target;
    try {
        target = normalizePathForComparison(realpath(targetPath), options);
    } catch (_) {
        return false;
    }
    if (!target) return false;
    return projects.some((project) => {
        const candidate = project && typeof project.path === 'string' ? project.path : '';
        try {
            return normalizePathForComparison(realpath(candidate), options) === target;
        } catch (_) {
            return false;
        }
    });
}

function extractGrpcStatus(responseBody, headers = {}, trailers = {}) {
    const body = Buffer.isBuffer(responseBody) ? responseBody : Buffer.from(responseBody || '');
    const directValues = [headers['grpc-status'], trailers['grpc-status']];
    for (const value of directValues) {
        const normalized = Array.isArray(value) ? value[0] : value;
        if (normalized !== undefined && normalized !== null && /^\d+$/.test(String(normalized))) {
            return Number(normalized);
        }
    }

    let offset = 0;
    while (offset + 5 <= body.length) {
        const flags = body[offset];
        const frameLength = body.readUInt32BE(offset + 1);
        const frameEnd = offset + 5 + frameLength;
        if (frameEnd > body.length) break;
        if ((flags & 0x80) !== 0) {
            const trailerText = body.subarray(offset + 5, frameEnd).toString('utf8');
            const match = trailerText.match(/^grpc-status:\s*(\d+)/im);
            if (match) return Number(match[1]);
        }
        offset = frameEnd;
    }

    const fallbackMatch = body.toString('utf8').match(/^grpc-status:\s*(\d+)/im);
    return fallbackMatch ? Number(fallbackMatch[1]) : null;
}

module.exports = {
    TEMP_CONVERSATION_ID_PATTERN,
    TemporaryConversationRegistry,
    OneShotPathLeaseRegistry,
    normalizePathForComparison,
    isRegisteredProjectPath,
    extractGrpcStatus,
};
