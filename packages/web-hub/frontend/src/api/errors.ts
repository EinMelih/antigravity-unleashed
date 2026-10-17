export interface ApiErrorOptions {
  code?: string;
  status?: number;
  technicalDetails?: string;
  requestId?: string;
  offline?: boolean;
}

export class ApiError extends Error {
  readonly code?: string;
  readonly status?: number;
  readonly technicalDetails?: string;
  readonly requestId?: string;
  readonly offline: boolean;

  constructor(message: string, options: ApiErrorOptions = {}) {
    super(message);
    this.name = "ApiError";
    this.code = options.code;
    this.status = options.status;
    this.technicalDetails = options.technicalDetails;
    this.requestId = options.requestId;
    this.offline = options.offline ?? false;
  }
}
