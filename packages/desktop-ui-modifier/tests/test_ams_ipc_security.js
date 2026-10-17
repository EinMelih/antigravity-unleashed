"use strict";

const assert = require('assert');
const path = require('path');

const {
    TemporaryConversationRegistry,
    OneShotPathLeaseRegistry,
    isRegisteredProjectPath,
    extractGrpcStatus,
} = require(path.join(__dirname, '..', 'src', 'amsIpcSecurity.js'));

const firstId = '11111111-1111-4111-8111-111111111111';
const secondId = '22222222-2222-4222-8222-222222222222';
let now = 1000;
const registry = new TemporaryConversationRegistry({ ttlMs: 100, now: () => now });

assert.throws(() => registry.register('../real-chat'), /valid UUID/);
assert.throws(() => registry.require(firstId), /not registered/);
assert.strictEqual(registry.register(firstId), firstId);
assert.strictEqual(registry.require(firstId), firstId);
now = 1099;
assert.strictEqual(registry.require(firstId), firstId);
now = 1100;
assert.throws(() => registry.require(firstId), /not registered/);
registry.register(secondId);
assert.strictEqual(registry.delete(secondId), true);
assert.throws(() => registry.require(secondId), /not registered/);

assert.strictEqual(extractGrpcStatus(Buffer.alloc(0), { 'grpc-status': '0' }), 0);
assert.strictEqual(extractGrpcStatus(Buffer.alloc(0), {}, { 'grpc-status': ['7'] }), 7);

const trailer = Buffer.from('grpc-status: 0\r\ngrpc-message: OK\r\n', 'utf8');
const trailerFrame = Buffer.alloc(5 + trailer.length);
trailerFrame[0] = 0x80;
trailerFrame.writeUInt32BE(trailer.length, 1);
trailer.copy(trailerFrame, 5);
assert.strictEqual(extractGrpcStatus(trailerFrame), 0);

const malformedFrame = Buffer.from([0x80, 0, 0, 1, 0]);
assert.strictEqual(extractGrpcStatus(malformedFrame), null);
assert.strictEqual(extractGrpcStatus(Buffer.from('no grpc trailer')), null);

let leaseNow = 10_000;
const leases = new OneShotPathLeaseRegistry({ ttlMs: 500, now: () => leaseNow });
leases.issue(17, 'C:\\Projects\\Demo');
assert.strictEqual(leases.consume(17), 'C:\\Projects\\Demo');
assert.strictEqual(leases.consume(17), null, 'workspace lease must be one-shot');
leases.issue(17, 'C:\\Projects\\Demo');
leaseNow += 500;
assert.strictEqual(leases.consume(17), null, 'expired workspace lease must fail closed');

const winOptions = {
    pathImpl: path.win32,
    platform: 'win32',
    realpath: (value) => value,
};
assert.strictEqual(isRegisteredProjectPath(
    [{ path: 'C:\\Projects\\Demo' }],
    'c:\\projects\\DEMO\\',
    winOptions,
), true);
assert.strictEqual(isRegisteredProjectPath(
    [{ path: 'C:\\Projects\\Demo' }],
    'C:\\Projects\\Other',
    winOptions,
), false);
assert.strictEqual(isRegisteredProjectPath([{ name: 'missing path' }], 'C:\\Projects\\Demo', winOptions), false);

console.log('amsIpcSecurity tests passed');
