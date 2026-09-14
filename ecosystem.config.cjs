module.exports = {
  apps: [
    {
      name: "dgask-kr-api",
      script: "server/src/index.js",
      interpreter: "node",
      instances: 1,
      exec_mode: "fork",
      env: {
        NODE_ENV: "production",
        PORT: 8080,
      },
      error_file: "logs/api-error.log",
      out_file: "logs/api-out.log",
      time: true,
    },
  ],
};
