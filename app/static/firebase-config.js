// Firebase Phone Auth Configuration (10,000 Free SMS / month)
// Get these values from: Firebase Console -> Project Settings -> General -> Your apps -> Web app
window.firebaseConfig = {
  apiKey: "",
  authDomain: "",
  projectId: "",
  storageBucket: "",
  messagingSenderId: "",
  appId: ""
};

(function initFirebase() {
  if (typeof firebase !== "undefined" && window.firebaseConfig && window.firebaseConfig.apiKey) {
    try {
      if (!firebase.apps.length) {
        firebase.initializeApp(window.firebaseConfig);
      }
    } catch (err) {
      console.warn("Firebase initialization:", err);
    }
  }
})();
