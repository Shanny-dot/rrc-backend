from app.core.supabase_client import supabase_admin
from fastapi import HTTPException
import uuid

class PointsService:
    @staticmethod
    def award_points(user_id: str, points: int, type: str, description: str, reference_id: str = None):
        """
        Awards points to a user and logs the transaction.
        Uses admin client to bypass RLS.
        """
        try:
            # 1. Update user total_points
            user_resp = supabase_admin.table("users").select("total_points").eq("id", user_id).single().execute()
            if not user_resp.data:
                raise Exception("User not found")
            
            new_total = user_resp.data["total_points"] + points
            supabase_admin.table("users").update({"total_points": new_total}).eq("id", user_id).execute()

            # 2. Insert transaction log
            transaction_data = {
                "user_id": user_id,
                "type": type,
                "points": points,
                "description": description
            }
            if reference_id:
                transaction_data["reference_id"] = reference_id
                
            supabase_admin.table("transactions").insert(transaction_data).execute()
            
            return True
        except Exception as e:
            print(f"Error awarding points: {e}")
            raise HTTPException(status_code=500, detail="Failed to award points")

    @staticmethod
    def deduct_points(user_id: str, points: int, type: str, description: str, reference_id: str = None):
        """
        Deducts points for redemptions. Checks balance first.
        """
        try:
            # 1. Check user total_points
            user_resp = supabase_admin.table("users").select("total_points").eq("id", user_id).single().execute()
            if not user_resp.data:
                 raise Exception("User not found")
            
            current_total = user_resp.data["total_points"]

            if current_total < points:
                raise Exception("Insufficient points")
                
            new_total = current_total - points
            supabase_admin.table("users").update({"total_points": new_total}).eq("id", user_id).execute()

            # 2. Insert transaction log (points are negative here generally based on logic, but typically we store absolute in transactions or negative. Assuming table schema takes negative)
            transaction_data = {
                "user_id": user_id,
                "type": type,
                "points": -abs(points), # Ensure it's negative
                "description": description
            }
            if reference_id:
                transaction_data["reference_id"] = reference_id
                
            supabase_admin.table("transactions").insert(transaction_data).execute()
            
            return True
        except Exception as e:
            print(f"Error deducting points: {e}")
            if "Insufficient" in str(e):
                raise HTTPException(status_code=400, detail="Insufficient points balance")
            raise HTTPException(status_code=500, detail="Failed to process point deduction")
