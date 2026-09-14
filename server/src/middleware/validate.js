import { HttpError } from "./errors.js";

export function validate(schema, source = "body") {
  return (req, _res, next) => {
    const { error, value } = schema.validate(req[source], {
      abortEarly: false,
      stripUnknown: true,
      convert: true,
    });
    if (error) {
      return next(new HttpError(400, "Validation failed", error.details.map((item) => item.message)));
    }
    req[source] = value;
    return next();
  };
}
