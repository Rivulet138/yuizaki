export default async ({ context }) => ({
  status: 200,
  body: {
    policy: context.policy,
  },
})
