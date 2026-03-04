import inspect
from supabase._sync.auth import SyncGoTrueClient

print("SyncGoTrueClient.sign_in_with_otp signature:", inspect.signature(SyncGoTrueClient.sign_in_with_otp))
print("SyncGoTrueClient.verify_otp signature:", inspect.signature(SyncGoTrueClient.verify_otp))
