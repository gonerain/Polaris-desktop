import { Type } from '@earendil-works/pi-ai';
import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { install } from './runtime.mjs';
export default function(pi: ExtensionAPI) { install(pi, Type.Object({name:Type.Optional(Type.String({maxLength:256}))})); }
