export class HttpError extends Error {
  constructor(status, message, details = null) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

export function notFound(_req, _res, next) {
  next(new HttpError(404, "Route not found"));
}

export function errorHandler(error, _req, res, _next) {
  const status = error.status || error.statusCode || 500;
  res.status(status).json({
    message: status === 500 ? "Internal server error" : error.message,
    details: error.details || undefined,
  });
}
