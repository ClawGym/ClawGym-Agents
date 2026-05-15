using UnityEngine;
using UnityEngine.Networking;
using System.Collections;

public class Telemetry : MonoBehaviour {
    public const string API_KEY = "sk_live_12345SECRET"; // TODO: remove before release
    [SerializeField] private string studentEmail = "student@example.edu"; // demo placeholder
    private string endpoint = "http://telemetry.art-school.local/collect"; // NOTE: http

    IEnumerator Send() {
        string deviceId = SystemInfo.deviceUniqueIdentifier;
        WWWForm form = new WWWForm();
        form.AddField("email", studentEmail);
        form.AddField("deviceId", deviceId);
        form.AddField("key", API_KEY);
        using (UnityWebRequest www = UnityWebRequest.Post(endpoint, form)) {
            yield return www.SendWebRequest();
            if (www.result != UnityWebRequest.Result.Success) {
                Debug.LogWarning("telemetry failed: " + www.error);
            } else {
                Debug.Log("telemetry ok");
            }
        }
    }

    void Start() {
        StartCoroutine(Send());
    }
}
